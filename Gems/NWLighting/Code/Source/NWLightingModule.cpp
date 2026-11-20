/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 */

#include "NWLightingModule.h"
#include <NWLighting/Components/NWEnvironmentComponent.h>

namespace NWLighting
{
    NWLightingModule::NWLightingModule()
    {
        m_descriptors.insert(m_descriptors.end(), {
            NWEnvironmentComponent::CreateDescriptor(),
        });
    }

    AZ::ComponentTypeList NWLightingModule::GetRequiredSystemComponents() const
    {
        return AZ::ComponentTypeList{};
    }
}

#if !defined(NWLIGHTING_GEM_EDITOR)
#if defined(O3DE_GEM_NAME)
AZ_DECLARE_MODULE_CLASS(AZ_JOIN(Gem_, O3DE_GEM_NAME), NWLighting::NWLightingModule)
#else
AZ_DECLARE_MODULE_CLASS(Gem_NWLighting, NWLighting::NWLightingModule)
#endif
#endif
