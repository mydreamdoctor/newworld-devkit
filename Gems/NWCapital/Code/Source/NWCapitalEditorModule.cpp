/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * For complete copyright and license terms please see the LICENSE at the root of this distribution.
 *
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 *
 */

#include "NWCapitalEditorModule.h"
#include "Editor/EditorCapitalCookieGradientComponent.h"

namespace NWCapital
{
    NWCapitalEditorModule::NWCapitalEditorModule()
        : NWCapitalModule()
    {
        m_descriptors.insert(m_descriptors.end(), {
            EditorCapitalCookieGradientComponent::CreateDescriptor(),
        });
    }

    AZ::ComponentTypeList NWCapitalEditorModule::GetRequiredSystemComponents() const
    {
        return NWCapitalModule::GetRequiredSystemComponents();
    }
}

#if defined(O3DE_GEM_NAME)
AZ_DECLARE_MODULE_CLASS(AZ_JOIN(Gem_, O3DE_GEM_NAME, _Editor), NWCapital::NWCapitalEditorModule)
#else
AZ_DECLARE_MODULE_CLASS(Gem_NWCapital_Editor, NWCapital::NWCapitalEditorModule)
#endif
