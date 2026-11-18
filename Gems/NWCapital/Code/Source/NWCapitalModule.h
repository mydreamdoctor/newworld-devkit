/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * For complete copyright and license terms please see the LICENSE at the root of this distribution.
 *
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 *
 */

#pragma once

#include <AzCore/Module/Module.h>

namespace NWCapital
{
    class NWCapitalModule
        : public AZ::Module
    {
    public:
        AZ_RTTI(NWCapitalModule, "{8E2B4A6C-1D5F-4E7A-9B3C-6D8E2F4A5B05}", AZ::Module);

        NWCapitalModule();
        ~NWCapitalModule() override = default;

        AZ::ComponentTypeList GetRequiredSystemComponents() const override;
    };
}
